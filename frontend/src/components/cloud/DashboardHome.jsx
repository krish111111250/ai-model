import { useState } from 'react';
import ApiPlayground from '@/components/cloud/ApiPlayground';
import DocumentManager from '@/components/cloud/DocumentManager';

/**
 * The workspace: the two things a customer uses day to day.
 *
 * The document list stays local to this page rather than going up to the
 * layout, because the playground is the only other thing that reads it - it
 * needs the list to offer a document to ask about - and both live here.
 */
const DashboardHome = () => {
  const [documents, setDocuments] = useState([]);

  return (
    <>
      <h1 className="text-xl font-semibold tracking-tight">Workspace</h1>
      <p className="mt-1.5 text-sm text-muted-foreground">
        Your documents, and a place to ask them questions.
      </p>

      <div className="mt-6">
        <DocumentManager onDocuments={setDocuments} />
      </div>

      <div className="mt-12 border-t border-border pt-12">
        <ApiPlayground documents={documents} />
      </div>
    </>
  );
};

export default DashboardHome;
